from .nodes import MiniMaxH3PromptPolishExtension


async def comfy_entrypoint():
    return MiniMaxH3PromptPolishExtension()
