import os

from deepagents import create_deep_agent
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver

load_dotenv()
from core import build_llm_client, load_app_config

with PostgresSaver.from_conn_string(
	conn_string=os.getenv("POSTGRES_URL"),
) as checkpointer:
	checkpointer.setup()
	
	cfg = load_app_config()
	model = build_llm_client(cfg.llm)
	
	agent = create_deep_agent(
		model=model,
		checkpointer=checkpointer
	)
	
	res = agent.invoke(
		input={
			"messages": [
				HumanMessage(content="我喜欢什么？")
			],
		},
		config=RunnableConfig(configurable={
			"thread_id": "123"
		})
	)
	
	print(res)
