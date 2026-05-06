"""Config loader with YAML + environment variable override support.

Environment variables override YAML values using double-underscore notation:
  MULTITF_BROKER__INITIAL_EQUITY=500
  MULTITF_RISK_WRAPPER__ENABLED=false
"""
import os
from pathlib import Path
from typing import Optional, Any

from .models import PlatformConfig


def load_yaml(path: Path) -> dict:
    """Load YAML file to dict. Falls back to JSON if yaml not installed."""
    try:
        import yaml
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        import json
        # If yaml not available, try json
        if path.suffix == ".json":
            with open(path, "r") as f:
                return json.load(f)
        raise ImportError("PyYAML required for .yaml configs. Install: pip install pyyaml")


def apply_env_overrides(config_dict: dict, prefix: str = "MULTITF") -> dict:
    """Apply environment variable overrides to config dict.
    
    MULTITF_STRATEGY__SYMBOL=XAUUSD -> config["strategy"]["symbol"] = "XAUUSD"
    MULTITF_BROKER__LEVERAGE=500 -> config["broker"]["leverage"] = 500
    """
    for key, value in os.environ.items():
        if not key.startswith(prefix + "_"):
            continue
        
        # MULTITF_STRATEGY__SYMBOL -> strategy.symbol
        path = key[len(prefix) + 1:].lower().split("__")
        
        # Navigate to the right nested dict
        target = config_dict
        for part in path[:-1]:
            target = target.setdefault(part, {})
        
        # Convert value to appropriate type
        final_key = path[-1]
        target[final_key] = _coerce_value(value)
    
    return config_dict


def _coerce_value(value: str) -> Any:
    """Coerce string env value to int/float/bool/str."""
    value = value.strip()
    
    # bool
    lower = value.lower()
    if lower in ("true", "yes", "1"):
        return True
    if lower in ("false", "no", "0"):
        return False
    
    # int
    try:
        return int(value)
    except ValueError:
        pass
    
    # float
    try:
        return float(value)
    except ValueError:
        pass
    
    # str
    return value


def load_config(path: Optional[Path] = None) -> PlatformConfig:
    """Load platform config from YAML with env overrides.
    
    Args:
        path: Path to config file. Defaults to config/platform.yaml in project root.
    
    Returns:
        Validated PlatformConfig instance.
    """
    if path is None:
        path = Path(__file__).parent.parent.parent.parent / "config" / "platform.yaml"
    
    config_dict = load_yaml(path)
    config_dict = apply_env_overrides(config_dict)
    
    return PlatformConfig(**config_dict)
