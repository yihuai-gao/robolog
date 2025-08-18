import os
from typing import Any, Dict, List, Optional
from loguru import logger
from robotmq import RMQClient, deserialize, serialize
from robologger.loggers.base_logger import BaseLogger
from robologger.utils.stdout_setup import setup_logging

class MainLogger:
    def __init__(
        self,
        name: str,
        root_dir: str,
        project_name: str,
        task_name: str,
        run_name: str,
        logger_endpoints: Dict[str, str], # {logger_name: logger_endpoint}
        # attr: dict,
    ):
        setup_logging()
        
        self.root_dir = root_dir
        self.project_name = project_name
        self.task_name = task_name
        self.run_name = run_name
        self.run_dir: str = os.path.join(self.root_dir, self.project_name, self.task_name, self.run_name)
        
        if not os.path.exists(self.run_dir):
            logger.info(f"Creating run directory: {self.run_dir}")
            os.makedirs(self.run_dir)
        self.clients: Dict[str, RMQClient] = {}

        self.logger_endpoints: Dict[str, str] = logger_endpoints

        for logger_name, logger_endpoint in logger_endpoints.items():
            self.clients[logger_name] = RMQClient(client_name=logger_name, server_endpoint=logger_endpoint)

        self.episode_idx: int = -1

    def validate_logger_endpoints(self):
        for logger_name, client in self.clients.items():
            topic_status = client.get_topic_status(topic="info", timeout_s=0.1)
            if topic_status <= 0:
                raise RuntimeError(f"Logger {logger_name} is not alive")
            raw_data, _ = client.peek_data(topic="info", n=1)
            data = deserialize(raw_data[0])
            if data["name"] != logger_name:
                raise RuntimeError(f"Requesting endpoint {self.logger_endpoints[logger_name]}, should be {logger_name}, but got {data['name']}")

    def start_recording(self, episode_idx: Optional[int] = None):
        self.validate_logger_endpoints()

        if episode_idx is not None:
            self.episode_idx = episode_idx
        else:
            self.episode_idx = self._get_next_episode_idx()
        assert self.episode_idx >= 0, "Episode index must be non-negative"
        logger.info(f"Starting episode {self.episode_idx}")

        episode_dir = os.path.join(self.run_dir, f"episode_{self.episode_idx:06d}")
        if not os.path.exists(episode_dir):
            os.makedirs(episode_dir)

        for logger_name, logger_endpoint in self.logger_endpoints.items():
            self.clients[logger_name].put_data(topic="command", data=serialize({"type": "start", "episode_dir": episode_dir}))

    def get_alive_loggers(self) -> List[str]:
        alive_loggers: List[str] = []
        for logger_name, client in self.clients.items():
            topic_status = client.get_topic_status(topic="info", timeout_s=0.1)
            if topic_status >= 0:
                alive_loggers.append(logger_name)
            else:
                logger.warning(f"Logger {logger_name} is not alive")
        return alive_loggers

    def stop_recording(self):
        alive_loggers = self.get_alive_loggers()
        for logger_name in alive_loggers:
            self.clients[logger_name].put_data(topic="command", data=serialize({"type": "stop"}))
        logger.info(f"Stopped recording for {len(alive_loggers)} loggers")

    def _get_next_episode_idx(self) -> int:
        """Find the next available episode index"""
        if not os.path.exists(self.run_dir):
            return 0
        
        existing_episodes = []
        for item in os.listdir(self.run_dir):
            if item.startswith("episode_") and os.path.isdir(os.path.join(self.run_dir, item)):
                try:
                    episode_num = int(item.split("_")[1])
                    existing_episodes.append(episode_num)
                except (IndexError, ValueError):
                    logger.warning(f"Invalid episode directory name: {item}")
                    continue
        
        return max(existing_episodes, default=-1) + 1