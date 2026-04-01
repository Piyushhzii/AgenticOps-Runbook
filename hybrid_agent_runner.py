'''from db_reader import get_steps
from runbook_selector import select_runbook


def run_agent():

    user_issue = input("Describe your issue: ")
    runbook_id = select_runbook(user_issue)

    print(f"\nSelected Runbook: {runbook_id}")

    steps = get_steps(runbook_id)

    # Sort steps by order
    ordered_steps = sorted(
        steps.items(),
        key=lambda x: x[1]["step_order"]
    )

    for step_id, step_data in ordered_steps:

        print(f"\nSTEP {step_data['step_order']}: {step_data['instruction']}")

        if step_data["step_type"] == "input":
            user_input = input("User: ")

            if user_input.lower() == "exit":
                print("\nExiting runbook...")
                return

    print("\nRunbook completed.")


run_agent()'''


from db_reader import get_steps
from runbook_selector import select_runbook
from step_reasoner import decide_next_step


def is_branch_step(instruction: str) -> bool:
    """
    Detect if step needs LLM reasoning.
    """
    instruction = instruction.strip().lower()
    return instruction.startswith("if") or instruction.startswith("based on")


def format_steps_for_prompt(steps: dict) -> str:
    """
    Convert DB steps into formatted string for LLM prompt.
    """
    formatted = ""
    for step_id, step_data in steps.items():
        formatted += f"{step_id} (Order {step_data['step_order']}): {step_data['instruction']}\n"
    return formatted


def run_agent():
    #Select Runbook
    user_issue = input("Describe your issue: ")
    runbook_id = select_runbook(user_issue)

    print(f"\nSelected Runbook: {runbook_id}")

    steps = get_steps(runbook_id)

    if not steps:
        print("No steps found for this runbook.")
        return

    #Order Steps
    ordered_steps = sorted(
        steps.items(),
        key=lambda x: x[1]["step_order"]
    )

    ordered_ids = [step_id for step_id, _ in ordered_steps]

    formatted_steps = format_steps_for_prompt(steps)

    executed_steps = []
    context = {}

    current_index = 0

    #Execution Loop
    while current_index < len(ordered_ids):

        step_id = ordered_ids[current_index]
        step = steps[step_id]

        print(f"\nSTEP {step['step_order']}: {step['instruction']}")

        executed_steps.append(step_id)

        user_response = ""

        # Handle Input Step
        if step["step_type"] == "input":

            user_response = input("User: ")

            if user_response.lower() == "exit":
                print("Exiting runbook execution.")
                return

            context[step_id] = user_response

        #Simulating System Checks
        #Replacing with real API's later
        elif "payment status" in step["instruction"].lower():
            print("System: Payment status = FAILED")
            context["payment_status"] = "FAILED"

        elif "admin system" in step["instruction"].lower():
            print("System: Account status = LOCKED")
            context["account_status"] = "LOCKED"


        # Determine Allowed Next Steps       
        allowed_next_steps = []

        if current_index + 1 < len(ordered_ids):
            next_step_id = ordered_ids[current_index + 1]

            # Prevent revisiting steps
            if next_step_id not in executed_steps:
                allowed_next_steps.append(next_step_id)

       
        if is_branch_step(step["instruction"]):

            next_step = decide_next_step(
                runbook_steps=formatted_steps,
                current_step=step_id,
                user_response=user_response,
                executed_steps=executed_steps,
                context=context,
                allowed_next_steps=allowed_next_steps
            )

            if next_step == "END":
                break

            if next_step in ordered_ids:
                current_index = ordered_ids.index(next_step)
            else:
                print("Invalid next step returned. Ending execution.")
                break

        else:
            #deterministic forward move
            current_index += 1

    print("\nRunbook execution completed.")


run_agent()