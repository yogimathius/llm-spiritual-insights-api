import json
import logging
from textwrap import dedent

from ai_app.models.llm_role import LLMRole
from ai_app.services.model_rotation import OpenAIService

logger = logging.getLogger("ai_app")

# Prompt Templates
FIRST_SPEAKER_INSTRUCTIONS = """
- Present your tradition's core perspective
- Identify potential areas of philosophical tension
- Establish key principles that others might challenge"""

RESPONDER_INSTRUCTIONS = """
- Challenge assumptions in previous responses
- Present counter-arguments from your tradition
- Propose alternative interpretations
- Push for greater precision in key concepts"""

DEBATE_PROMPT_TEMPLATE = """You are {name}: {description}

You are {position_context}in this debate about: "{user_prompt}"

Previous perspectives:
{dialogue_context}

As we are in debate mode, engage critically with the discussion by:
{debate_instructions}

Keep your response focused and under 150 words.

Question: {user_prompt}"""

DIALOGUE_PROMPT_TEMPLATE = """You are {name}: {description}

Previous perspectives on "{user_prompt}":
{dialogue_context}

Your task is to evolve this dialogue by:
1. Deeply engaging with the previous perspectives:
   - Identify key insights or concepts from previous responses
   - Find points of resonance or harmony with your tradition
   - Build upon metaphors or analogies introduced by others

2. Weaving connections:
   - Draw parallels between different viewpoints shared
   - Bridge seemingly disparate perspectives
   - Reveal hidden connections between different traditions' approaches

3. Advancing the dialogue:
   - Introduce a new dimension to the discussion
   - Deepen shared insights
   - Offer practical implications of the combined wisdom

4. Speaking authentically as {name}:
   - Ground your response in your unique spiritual framework
   - Share specific wisdom from your tradition that illuminates the discussion
   - Maintain your distinct voice while building on others

Keep your response focused and under 150 words.

Question: {user_prompt}"""

SYNTHESIS_PROMPT_TEMPLATE = """You are tasked with synthesizing this multi-perspective dialogue about: "{user_prompt}"

Complete dialogue:
{dialogue_context}

Please provide:
1. Key insights from each perspective
2. Main points of agreement and disagreement
3. A final synthesis that weaves these viewpoints together

Keep your response concise and under 250 words."""


class DialogueGenerator:
    def __init__(self, openai_service: OpenAIService):
        self.openai_service = openai_service

    def get_collaboration_decision(self, role, user_prompt, collaborators):
        collaborator_list = "\n".join(
            [
                f"- {c.name}: {c.description} (Triggers: {c.collaboration_triggers})"
                for c in collaborators
            ]
        )

        system_prompt = dedent(
            f"""You are {role.name}. Your task is to decide if collaboration would be valuable for answering the user's question."""
        )

        collaboration_context = dedent(
            f"""User question: "{user_prompt}"
            You have access to the following potential collaborators:
            {collaborator_list}

            Please respond in JSON format with the following structure:
            {{
                "should_collaborate": true/false,
                "chosen_collaborator": "Name of chosen collaborator",
                "reasoning": "Brief explanation of your decision"
            }}"""
        )

        content = self.openai_service.create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": collaboration_context},
            ]
        )
        clean_content = content.replace("```json\n", "").replace("\n```", "").strip()
        return json.loads(clean_content)

    def create_system_prompt(self, role, collab_decision):
        """Helper function to create system prompt based on collaboration decision"""
        json_instruction = """
        IMPORTANT: Your response must be valid JSON. Always wrap your response in square brackets,
        use double quotes for strings, and ensure proper JSON formatting.
        """

        if collab_decision.get("should_collaborate"):
            try:
                collaborator = LLMRole.objects.get(name=collab_decision["chosen_collaborator"])
                return dedent(
                    f"""
                    You are hosting a dialogue between {role.name} and {collaborator.name}.

                    Primary Perspective ({role.name}): {role.description}
                    Collaborative Perspective ({collaborator.name}): {collaborator.description}

                    Reason for collaboration: {collab_decision["reasoning"]}

                    {json_instruction}
                    Format your response exactly like this:
                    [
                        {{"role": "{role.name}", "response": "Initial perspective"}},
                        {{"role": "{collaborator.name}", "response": "Response"}},
                        {{"role": "{role.name}", "response": "Building on insights"}},
                        {{"role": "{collaborator.name}", "response": "Final insights"}},
                        {{"role": "Synthesis", "response": "Brief conclusion"}}
                    ]
                    """
                )
            except LLMRole.DoesNotExist:
                logger.error(f"Collaborator not found: {collab_decision['chosen_collaborator']}")
                return role.prompt_template

        return dedent(
            f"""
            You are {role.name}.

            {role.prompt_template}

            {json_instruction}
            Format your response exactly like this:
            [
                {{"role": "{role.name}", "response": "Your complete response here"}}
            ]
        """
        )

    def generate_role_response(self, role, user_prompt, dialogue_context="", should_debate=False):
        is_first = not bool(dialogue_context.strip())
        position_context = (
            "the first speaker " if is_first else "responding to previous perspectives "
        )
        debate_instructions = FIRST_SPEAKER_INSTRUCTIONS if is_first else RESPONDER_INSTRUCTIONS

        template = DEBATE_PROMPT_TEMPLATE if should_debate else DIALOGUE_PROMPT_TEMPLATE
        role_prompt = template.format(
            name=role.name,
            description=role.description,
            user_prompt=user_prompt,
            dialogue_context=dialogue_context,
            position_context=position_context,
            debate_instructions=debate_instructions,
        )

        return self.openai_service.create_completion(
            messages=[
                {"role": "system", "content": role.prompt_template},
                {"role": "user", "content": role_prompt},
            ],
            temperature=0.7,
            max_tokens=200,
        )

    def generate_synthesis(self, user_prompt, dialogue_context):
        synthesis_prompt = SYNTHESIS_PROMPT_TEMPLATE.format(
            user_prompt=user_prompt, dialogue_context=dialogue_context
        )

        return self.openai_service.create_completion(
            messages=[
                {
                    "role": "system",
                    "content": "You are synthesizing a philosophical dialogue.",
                },
                {"role": "user", "content": synthesis_prompt},
            ],
            temperature=0.7,
            max_tokens=400,
        )

    def process_single_role(self, role_name: str, user_prompt: str) -> dict:
        """Handle single role dialogue with optional collaboration"""
        role = LLMRole.objects.prefetch_related("collaborators").get(name=role_name)
        collaborators = role.collaborators.all()
        collab_decision = self.get_collaboration_decision(role, user_prompt, collaborators)
        system_prompt = self.create_system_prompt(role, collab_decision)

        # Increase max_tokens for collaborative responses
        max_tokens = 600 if collab_decision.get("should_collaborate") else 300

        content = self.openai_service.create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=max_tokens,  # Increased token limit
        )

        try:
            clean_content = content.replace("```json\n", "").replace("\n```", "").strip()

            try:
                parsed_data = json.loads(clean_content)
                if not isinstance(parsed_data, list):
                    parsed_data = [{"role": role.name, "response": clean_content}]

                # Check for and handle incomplete responses
                for item in parsed_data:
                    if not isinstance(item, dict):
                        continue
                    response_text = item.get("response", "")
                    if response_text.endswith(("...", ".", ",")):
                        # Trim incomplete sentences
                        last_sentence = response_text.rstrip(".,").rsplit(".", 1)[0]
                        item["response"] = last_sentence + "."

                response_data = parsed_data

            except json.JSONDecodeError:
                logger.warning("Failed to parse JSON response from model.")
                response_data = [{"role": role.name, "response": clean_content}]

            return {
                "response_data": response_data,
                "collab_decision": collab_decision,
                "role": role,
                "raw_content": content,
            }

        except Exception as e:
            logger.error("Error processing response: %s", type(e).__name__)
            return {
                "response_data": [{"role": role.name, "response": "Error processing response"}],
                "collab_decision": collab_decision,
                "role": role,
                "raw_content": content,
            }

    def process_full_dialogue(self, user_prompt: str, should_debate: bool) -> dict:
        """Handle multi-role dialogue with synthesis"""
        roles = list(LLMRole.objects.all())

        conversation = []
        dialogue_context = ""

        for i, role in enumerate(roles):
            try:
                role_response = self.generate_role_response(
                    role=role,
                    user_prompt=user_prompt,
                    dialogue_context=dialogue_context,
                    should_debate=should_debate,
                )

                conversation.append({"turn": i + 1, "role": role.name, "response": role_response})

                dialogue_context += f"\n\n{role.name}: {role_response}"

            except Exception as e:
                logger.error("Error getting response for %s: %s", role.name, type(e).__name__)
                continue

        final_response = None
        if conversation:
            try:
                final_response = self.generate_synthesis(
                    user_prompt=user_prompt, dialogue_context=dialogue_context
                )

                conversation.append(
                    {
                        "turn": len(conversation) + 1,
                        "role": "Synthesis",
                        "response": final_response,
                    }
                )

            except Exception as e:
                logger.error("Error generating synthesis: %s", type(e).__name__)
                raise

        return {
            "conversation": conversation,
            "final_analysis": final_response,
            "dialogue_context": dialogue_context,
        }

    def stream_full_dialogue(self, user_prompt: str, should_debate: bool):
        """Stream each role's response as it's generated"""
        roles = list(LLMRole.objects.all())

        dialogue_context = ""

        for i, role in enumerate(roles):
            try:
                # First yield a "thinking" message
                yield {"type": "thinking", "data": {"turn": i + 1, "role": role.name}}

                # Generate and yield the response
                role_response = self.generate_role_response(
                    role=role,
                    user_prompt=user_prompt,
                    dialogue_context=dialogue_context,
                    should_debate=should_debate,
                )

                response_data = {
                    "type": "response",
                    "data": {
                        "turn": i + 1,
                        "role": role.name,
                        "response": role_response,
                    },
                }

                dialogue_context += f"\n\n{role.name}: {role_response}"
                yield response_data

            except Exception as e:
                logger.error("Error getting response for %s: %s", role.name, type(e).__name__)
                yield {
                    "type": "error",
                    "data": {"role": role.name, "error": "Response generation failed"},
                }
                continue

        # Generate synthesis after all responses
        if dialogue_context:
            try:
                # Yield thinking message for synthesis
                yield {
                    "type": "thinking",
                    "data": {"turn": len(roles) + 1, "role": "Synthesis"},
                }

                final_response = self.generate_synthesis(
                    user_prompt=user_prompt, dialogue_context=dialogue_context
                )

                yield {
                    "type": "synthesis",
                    "data": {
                        "turn": len(roles) + 1,
                        "role": "Synthesis",
                        "response": final_response,
                    },
                }

            except Exception as e:
                logger.error("Error generating synthesis: %s", type(e).__name__)
                yield {
                    "type": "error",
                    "data": {"role": "Synthesis", "error": "Response generation failed"},
                }
