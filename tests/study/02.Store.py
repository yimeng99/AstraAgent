import os

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.postgres import PostgresStore

load_dotenv()
from core import build_llm_client, load_app_config

with PostgresStore.from_conn_string(
	conn_string=os.getenv("POSTGRES_URL"),
) as store:
	store.setup()
	
	cfg = load_app_config()
	model = build_llm_client(cfg.llm)
	
	agent = create_deep_agent(
		model=model,
		# 长期记忆
		memory=["/memories/AGENT.md"],
		backend=CompositeBackend(
			default=StateBackend(),
			routes={
				"/memories/": StoreBackend(
					namespace=lambda rt: (
						rt.context["assistant_id"]
					),
					store=store
				)
			}
		)
	)
	
	res = agent.invoke(
		input={
			"messages": [
				HumanMessage(content="我喜欢什么？")
			],
		},
		context={ "assistant_id": "123" }
	)
	
	print(res)
