"""Load configuration from the Git index."""

from prec.config.config import CONFIG_PATH, Config, loads_config
from prec.errors.errors import ConfigError
from prec.git.index import index_entries, read_index_blob
from prec.git.repository import Repository


def load_index_config(repository: Repository) -> Config:
    """Load and validate the configuration indexed for commit."""
    entries = index_entries(repository, CONFIG_PATH)
    if not entries:
        raise ConfigError(f"{CONFIG_PATH}: configuration is absent from the Git index")
    if len(entries) != 1 or entries[0].stage != 0:
        raise ConfigError(f"{CONFIG_PATH}: configuration has an unmerged index entry")
    mode = entries[0].mode
    if mode == "120000":
        raise ConfigError(f"{CONFIG_PATH}: indexed configuration must not be a symbolic link")
    if not mode.startswith("100"):
        raise ConfigError(f"{CONFIG_PATH}: indexed configuration is not a regular file")
    return loads_config(read_index_blob(repository, CONFIG_PATH))
