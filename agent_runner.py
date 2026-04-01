from db_reader import get_steps
from step_reasoner import decide_next_step
from runbook_selector import select_runbook


def run_agent():

    user_issue = input("Describe your issue: ")
    runbook_id = select_runbook(user_issue)

    print(f"\nSelected Runbook: {runbook_id}")

    steps = get_steps(runbook_id)

    current_step = list(steps.keys())[0]
    executed_steps = []   #track history

    while True:
        step = steps[current_step]

        print("\nSTEP:", step["instruction"])

        if step["step_type"] == "input":
            user_input = input("User: ")
        else:
            user_input = ""

        executed_steps.append(current_step)  #remember

        next_step = decide_next_step(
            steps,
            current_step,
            user_input,
            executed_steps   #pass to LLM
        )

        if next_step == "END":
            print("\nRunbook completed.")
            break

        current_step = next_step


run_agent()