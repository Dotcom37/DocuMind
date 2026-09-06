import os
from typing import Annotated, TypedDict

from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage
from langchain_tavily import TavilySearch
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from .rag import get_pdf_search_tool


class State(TypedDict):
    messages: Annotated[list, add_messages]


SYSTEM_MESSAGE = SystemMessage(
    content="""
You are a helpful assistant.

You have two tools:
1. pdf_search: use this for information contained in the PDF uploaded in the current chat session.
2. web_search: use this for current, recent, or up-to-date information from the web.

If a question can reasonably be answered from the uploaded PDF, prefer pdf_search.
Do not invent information. If the PDF does not contain the answer, say so.
"""
)


def build_graph(session_id: str, user_id: int):
    tools = [TavilySearch(max_results=2), get_pdf_search_tool(session_id, user_id)]
    llm = init_chat_model(
        model=os.getenv("CHAT_MODEL", "groq:openai/gpt-oss-120b")
    )
    llm_with_tools = llm.bind_tools(tools)

    def agent(state: State):
        response = llm_with_tools.invoke(state["messages"])

        print("LLM RESPONSE:", response)
        print("TOOL CALLS:", response.tool_calls)
        return {"messages": [response]}

    builder = StateGraph(State)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(tools))
    builder.add_conditional_edges(
        "agent", tools_condition, {"tools": "tools", "__end__": END}
    )
    builder.add_edge(START, "agent")
    builder.add_edge("tools", "agent")
    return builder.compile()


def generate_response(question: str, session_id: str, user_id: int):
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")
    graph = build_graph(session_id, user_id)
    result = graph.invoke(
        {"messages": [SYSTEM_MESSAGE, ("user", question)]}
    )
    return result["messages"][-1]

    
