\"\"\"Enhanced model router with dynamic model configuration support.\"\"\"

import logging
import re
import yaml
import os
from typing import AsyncGenerator, Optional
from .ollama_client import OllamaClient
from .claude_client import ClaudeClient

logger = logging.getLogger("nexus.router")

# Indicators that suggest a message needs complex reasoning
COMPLEX_INDICATORS = [
    r"\\b(analyse|analyze|explain|compare|contrast|evaluate|synthesize|critique)\\b",
    r"\\b(write|draft|compose|create)\\b.{10,}",  # writing tasks with detail
    r"\\b(code|implement|build|architect|debug|refactor)\\b",
    r"\\b(research|investigate|deep.?dive|thorough)\\b",
    r"\\b(strategy|plan|roadmap|design)\\b",
    r"\\b(why|how come|what causes|reasoning behind)\\b",
    r"\\b(step.by.step|break.?down|walk.me.through)\\b",
    r"\\b(pros?.and.cons?|trade.?offs?|advantages?.and.disadvantages?)\\b",
    r"```",  # code blocks suggest technical work
]

# Indicators for simple tasks suitable for local model
SIMPLE_INDICATORS = [
    r"^(hi|hello|hey|thanks|thank you|ok|okay|yes|no|sure)\\b",
    r"^(what is|who is|when was|where is|define)\\b.{0,50}$",
    r"^(translate|summarize|summarise|tldr)\\b",
    r"\\b(remind|timer|alarm|schedule)\\b",
    r"^.{0,80}$",  # very short messages
]


class ModelRouter:
    \"\"\"Enhanced router with dynamic model configuration support.\"\"\"

    def __init__(
        self,
        ollama,
        claude,
        complexity_threshold: int = 60,
    ):
        self.ollama = ollama
        self.claude = claude
        self.complexity_threshold = complexity_threshold
        self._ollama_available = False
        self._claude_available = False
        self._models_config = None
        self._load_models_config()

    def _load_models_config(self):
        \"\"\"Load model configuration from models.yaml if available.\"\"\"
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'models.yaml')
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    self._models_config = yaml.safe_load(f)
                logger.info("Loaded models configuration from models.yaml")
            else:
                logger.info("No models.yaml found, using default configuration")
        except Exception as e:
            logger.warning(f"Failed to load models.yaml: {e}")
            self._models_config = None

    def get_model_config(self, provider: str, model: str) -> Optional[dict]:
        \"\"\"Get configuration for a specific model.\"\"\"
        if not self._models_config:
            return None
        return self._models_config.get('models', {}).get(provider, {}).get(model)

    def resolve_alias(self, alias: str) -> Optional[str]:
        \"\"\"Resolve model alias to full model path.\"\"\"
        if not self._models_config:
            return None
        return self._models_config.get('aliases', {}).get(alias)

    async def check_availability(self):
        \"\"\"Check which models are available.\"\"\"
        if self.ollama:
            self._ollama_available = await self.ollama.is_available()
            logger.info(f"Ollama available: {self._ollama_available}")
        if self.claude:
            self._claude_available = await self.claude.is_available()
            logger.info(f"Claude available: {self._claude_available}")

        if not self._ollama_available and not self._claude_available:
            logger.error("No models available! Check Ollama and Anthropic API key.")

    def estimate_complexity(self, message: str) -> int:
        \"\"\"Estimate message complexity on a 0-100 scale.\"\"\"
        score = 50  # baseline

        # Check for complexity indicators
        for pattern in COMPLEX_INDICATORS:
            if re.search(pattern, message, re.IGNORECASE):
                score += 8

        # Check for simplicity indicators
        for pattern in SIMPLE_INDICATORS:
            if re.search(pattern, message, re.IGNORECASE):
                score -= 12

        # Length factor — longer messages tend to be more complex
        word_count = len(message.split())
        if word_count > 200:
            score += 15
        elif word_count > 100:
            score += 8
        elif word_count < 10:
            score -= 10

        # Multi-part questions
        question_marks = message.count("?")
        if question_marks > 2:
            score += 10

        return max(0, min(100, score))

    def select_model(self, message: str, force_model: str = None) -> str:
        \"\"\"Select which model to use. Returns 'claude', 'ollama', or raises.\"\"\"

        # Handle model aliases
        if force_model:
            # Check if it's an alias first
            resolved = self.resolve_alias(force_model)
            if resolved:
                provider, model = resolved.split('/')
                if provider == "claude" and self._claude_available:
                    # Update Claude client model if we have specific model config
                    model_config = self.get_model_config('claude', model)
                    if model_config and self.claude:
                        self.claude.model = model_config['name']
                        logger.info(f"Switched Claude model to: {model_config['name']}")
                    return "claude"
                elif provider == "local" and self._ollama_available:
                    return "ollama"

            # Legacy support
            if force_model == "claude" and self._claude_available:
                return "claude"
            elif force_model in ("ollama", "local") and self._ollama_available:
                return "ollama"
            elif force_model in ("opus", "sonnet", "haiku"):
                # Handle direct Claude model names
                if self._claude_available:
                    model_config = self.get_model_config('claude', force_model)
                    if model_config and self.claude:
                        self.claude.model = model_config['name']
                        logger.info(f"Switched Claude model to: {model_config['name']}")
                    return "claude"

        complexity = self.estimate_complexity(message)
        logger.info(f"Complexity score: {complexity}/{self.complexity_threshold}")

        if complexity >= self.complexity_threshold:
            # Prefer Claude for complex tasks
            if self._claude_available:
                return "claude"
            elif self._ollama_available:
                logger.warning("Claude unavailable, falling back to Ollama for complex task")
                return "ollama"
        else:
            # Prefer local for simple tasks
            if self._ollama_available:
                return "ollama"
            elif self._claude_available:
                logger.info("Ollama unavailable, using Claude for simple task")
                return "claude"

        raise RuntimeError("No models are currently available")

    def _get_client(self, model_name: str):
        if model_name == "claude":
            return self.claude
        return self.ollama

    async def chat(self, messages: list, system: str = None, force_model: str = None) -> dict:
        \"\"\"Route a chat request to the appropriate model.\"\"\"
        last_message = messages[-1]["content"] if messages else ""
        model_name = self.select_model(last_message, force_model)
        client = self._get_client(model_name)

        logger.info(f"Routing to: {model_name}")

        try:
            result = await client.chat(messages, system)
            result["routed_to"] = model_name
            return result
        except Exception as e:
            # Try fallback
            logger.warning(f"{model_name} failed: {e}. Trying fallback...")
            fallback = "claude" if model_name == "ollama" else "ollama"
            fallback_client = self._get_client(fallback)
            if fallback_client:
                result = await fallback_client.chat(messages, system)
                result["routed_to"] = fallback
                result["fallback"] = True
                return result
            raise

    async def chat_stream(
        self, messages: list, system: str = None, force_model: str = None
    ) -> tuple:
        \"\"\"Route a streaming chat request. Returns (model_name, stream).\"\"\"
        last_message = messages[-1]["content"] if messages else ""
        model_name = self.select_model(last_message, force_model)
        client = self._get_client(model_name)

        logger.info(f"Streaming via: {model_name}")
        return model_name, client.chat_stream(messages, system)

    @property
    def status(self) -> dict:
        \"\"\"Enhanced status with model configuration info.\"\"\"
        status = {
            "ollama_available": self._ollama_available,
            "claude_available": self._claude_available,
            "ollama_model": self.ollama.model if self.ollama else None,
            "claude_model": self.claude.model if self.claude else None,
            "complexity_threshold": self.complexity_threshold,
        }
        
        # Add model config info if available
        if self._models_config:
            status["configured_models"] = {
                "claude": list(self._models_config.get('models', {}).get('claude', {}).keys()),
                "local": list(self._models_config.get('models', {}).get('local', {}).keys())
            }
            status["aliases"] = self._models_config.get('aliases', {})
            
        return status
