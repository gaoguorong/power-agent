from typing import TypedDict, Annotated, Any, Dict, Optional

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    session_id: str
    question: str
    matched_skill: Optional[Dict[str, Any]]
    skill_route: Optional[str]