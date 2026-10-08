from deepagents import create_deep_agent
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

load_dotenv()
from core import build_llm_client, load_app_config

# 检查点
checkpointer = MemorySaver()

cfg = load_app_config()
model = build_llm_client(cfg.llm)


@tool
def remove_file(path: str) -> str:
	"""Delete a file from the filesystem."""
	return f"Deleted {path}"


@tool
def fetch_file(path: str) -> str:
	"""Read a file from the filesystem."""
	return f"Contents of {path}"


@tool
def notify_email(to: str, subject: str, body: str) -> str:
	"""Send an email."""
	return f"Sent email to {to}"


agent = create_deep_agent(
	model=model,
	tools=[remove_file, fetch_file, notify_email],
	# 人工介入
	interrupt_on={
		"remove_file": True,
		"fetch_file": True,
		"notify_email": True,
	},
	checkpointer=checkpointer
)
res = agent.invoke(
	{"messages": [{"role": "user", "content": "你好，帮我删除 /tmp/a.txt"}]},
	config=RunnableConfig(configurable={"thread_id": "user-1"}),  # 因为用了 checkpointer，必须传 thread_id
)

dec = [
	{ "type": "approve" }
]

res2 = agent.invoke(
	Command(resume={
		"decisions": dec
	}),
	config=RunnableConfig(configurable={"thread_id": "user-1"}),  # 因为用了 checkpointer，必须传 thread_id
)

print(res)
print(res2)
