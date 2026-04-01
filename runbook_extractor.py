import os
import json
from config_loader import llm_config
from prompts_loader import load_prompt
from langchain_groq import ChatGroq
from dotenv import load_dotenv

load_dotenv()

def extract_runbook(runbook_text):
    prompt_template = load_prompt("runbook_extraction")
    final_prompt = prompt_template.replace("{runbook_text}", runbook_text)

    llm = ChatGroq(
        groq_api_key=os.getenv("GROQ_API_KEY"),
        model=llm_config["llm"]["model"],
        temperature=llm_config["llm"]["temperature"]
    )

    response = llm.invoke(final_prompt)
    
    #parse JSON response before returning
    try:
        runbook_data = json.loads(response.content)
        print("JSON parsed successfully:", runbook_data.get("runbook_name", "Unknown"))
        return runbook_data
    except json.JSONDecodeError as e:
        print("JSON parse failed:", e)
        print("Raw response preview:", response.content[:300])
        # Fallback structure
        return {
            "runbook_name": "login_issue_fallback", 
            "issue_category": "unknown",
            "description": response.content[:500],
            "steps": []
        }
