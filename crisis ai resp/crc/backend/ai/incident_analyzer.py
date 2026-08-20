import os
import re

from .schemas import IncidentAnalysis


class IncidentAnalyzer:
    """Structured incident extraction with a deterministic local fallback."""

    def __init__(self, model=None):
        self.model = model or self._build_model()

    @staticmethod
    def _build_model():
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        try:
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0,
                api_key=api_key,
            ).with_structured_output(IncidentAnalysis)
        except Exception:
            return None

    async def analyze(self, description: str, location: str | None = None) -> IncidentAnalysis:
        if self.model is not None:
            try:
                result = await self.model.ainvoke([
                    (
                        "system",
                        "Extract emergency facts. Return only the requested structured schema. "
                        "Do not invent missing facts, units, locations, or distances. "
                        "Use CRITICAL for serious injury, active fire, immediate danger, or a blocked major road.",
                    ),
                    ("human", f"Location: {location or 'unknown'}\nReport: {description}"),
                ])
                return IncidentAnalysis.model_validate(result)
            except Exception:
                pass
        return self._fallback(description, location)

    @staticmethod
    def _fallback(description: str, location: str | None) -> IncidentAnalysis:
        text = description.lower()
        accident = bool(re.search(r"accident|crash|collision|pile[- ]?up", text))
        breakdown = bool(re.search(r"breakdown|flat tire|vehicle won.t start", text))
        fire = bool(re.search(r"fire|flames|burning|smoke", text))
        injury = bool(re.search(r"injur|casualt|wound|bleed|serious|critical", text))
        blocked = bool(re.search(r"block|blocking|closed|lane", text))
        danger = fire or injury or bool(re.search(r"immediate danger|explosion|armed", text))
        people_match = re.search(r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:people|persons|casualties|victims)", text)
        vehicles_match = re.search(r"(\d+)\s+(?:vehicles|cars|trucks)", text)

        if breakdown:
            incident_type = "vehicle_breakdown"
        elif accident:
            incident_type = "road_accident"
        elif fire:
            incident_type = "fire"
        elif re.search(r"medical|ambulance|heart|illness", text):
            incident_type = "medical"
        else:
            incident_type = "unknown"

        if fire or (accident and (injury or blocked)) or danger:
            severity = "CRITICAL"
        elif accident or injury:
            severity = "HIGH"
        elif breakdown:
            severity = "LOW"
        else:
            severity = "MEDIUM"

        services = []
        if accident:
            services.append("POLICE")
            if injury:
                services.append("AMBULANCE")
            if fire:
                services.append("FIRE_RESCUE")
        elif breakdown:
            services.append("HIGHWAY_ASSISTANCE")
        elif fire:
            services.extend(["FIRE_RESCUE", "AMBULANCE"] if injury else ["FIRE_RESCUE"])
        elif re.search(r"medical|ambulance|heart|illness", text):
            services.append("AMBULANCE")
        else:
            services.append("POLICE")

        reason = f"{severity.title()} {incident_type.replace('_', ' ')} reported. "
        reason += "Required services were selected from the reported hazards and injuries."
        return IncidentAnalysis(
            incident_type=incident_type,
            location=location,
            severity=severity,
            number_of_people=(
                int(people_match.group(1)) if people_match and people_match.group(1).isdigit()
                else {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                      "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}.get(people_match.group(1))
                if people_match else None
            ),
            injuries=injury,
            vehicles_involved=int(vehicles_match.group(1)) if vehicles_match else None,
            fire_present=fire,
            road_blocked=blocked,
            immediate_danger=danger,
            required_services=services,
            reasoning=reason,
        )
