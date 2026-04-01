'''import os
from langchain_groq import ChatGroq
from prompts_loader import load_prompt
from dotenv import load_dotenv

load_dotenv()


def decide_next_step(all_steps, current_step, user_response, executed_steps):

    llm = ChatGroq(
        groq_api_key=os.getenv("GROQ_API_KEY"),
        model="openai/gpt-oss-120b",
        temperature=0
    )

    prompt_template = load_prompt("step_reasoning")

    formatted_steps = "\n".join(
        [
            f"{sid} | Order:{data['step_order']} | {data['instruction']}"
            for sid, data in all_steps.items()
        ]
    )

    executed = ", ".join(executed_steps)

    prompt = prompt_template.format(
        runbook_steps=formatted_steps,
        executed_steps=executed,
        current_step=current_step,
        user_response=user_response
    )

    response = llm.invoke(prompt)
    return response.content.strip()'''


import os
from config_loader import llm_config
from prompts_loader import load_prompt
from langchain_groq import ChatGroq
from dotenv import load_dotenv

load_dotenv()


def decide_next_step(
    runbook_steps,
    current_step,
    user_response,
    executed_steps,
    context,
    allowed_next_steps
):

    #If nothing allowed immediately END
    if not allowed_next_steps:
        return "END"

    prompt_template = load_prompt("step_reasoning")

    final_prompt = prompt_template.format(
        runbook_steps=runbook_steps,
        current_step=current_step,
        user_response=user_response,
        executed_steps=executed_steps,
        context=context,
        allowed_next_steps=allowed_next_steps
    )

    llm = ChatGroq(
        groq_api_key=os.getenv("GROQ_API_KEY"),
        model=llm_config["llm"]["model"],
        temperature=llm_config["llm"]["temperature"]
    )

    response = llm.invoke(final_prompt)

    result = response.content.strip()

    #HARD SAFETY VALIDATION
    if result not in allowed_next_steps and result != "END":
        print("Invalid step returned by LLM. Falling back to safe sequential step.")
        return allowed_next_steps[0]

    return result
