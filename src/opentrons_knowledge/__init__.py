"""Opentrons Knowledge: corpus builder and consumer library."""

from opentrons_knowledge.__version__ import (
    BUILDER_NAME,
    CORPUS_SCHEMA_VERSION,
    PRODUCT_NAME,
    __version__,
)

__all__ = [
    "BUILDER_NAME",
    "CORPUS_SCHEMA_VERSION",
    "PRODUCT_NAME",
    "Corpus",
    "__version__",
]


def __getattr__(name: str) -> object:
    if name == "Corpus":
        from opentrons_knowledge.consumer.corpus import Corpus

        return Corpus
    raise AttributeError(name)
