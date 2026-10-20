from application.agents.classic_agent import ClassicAgent
from application.agents.react_agent import ReActAgent
import logging

logger = logging.getLogger(__name__)


class AgentCreator:
    agents = {
        "classic": ClassicAgent,
        "react": ReActAgent,
    }

    @classmethod
    def create_agent(cls, type, *args, **kwargs):
        agent_class = cls.agents.get(type.lower())
        if not agent_class:
            raise ValueError(f"No agent class found for type {type}")
        
        # Filter out kwargs that are not accepted by the agent's __init__
        import inspect
        init_params = inspect.signature(agent_class.__init__).parameters
        valid_kwargs = {k: v for k, v in kwargs.items() if k in init_params}
        
        return agent_class(*args, **valid_kwargs)
