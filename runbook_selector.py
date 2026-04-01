import os
from langchain_groq import ChatGroq
from prompts_loader import load_prompt
from config_loader import llm_config
from db_reader import get_all_runbooks
from dotenv import load_dotenv

load_dotenv()

def select_runbook(user_message: str) -> str:

    runbooks = get_all_runbooks()

    runbook_list = "\n".join(
        [f"{rb['runbook_id']} : {rb['description']}" for rb in runbooks]
    )

    prompt_template = load_prompt("runbook_selection")

    prompt = prompt_template.format(
        runbook_list=runbook_list,
        user_message=user_message
    )

    llm = ChatGroq(
        groq_api_key=os.getenv("GROQ_API_KEY"),
        model=llm_config["llm"]["model"],
        temperature=llm_config["llm"]["temperature"]
    )

    response = llm.invoke(prompt)
    return response.content.strip()
