---
title: "Python API: Loading Pipettes"
description: "Load single-channel, 8-channel, and 96-channel pipettes in protocols."
---

# Loading Pipettes

When writing a protocol, you must inform the Protocol API about the pipettes you will be using.
See [`load_instrument()`][opentrons.protocol_api.ProtocolContext.load_instrument].

## API load names

=== "Flex"

    ```python
    # Flex 1-Channel in the left mount
    pipette = protocol.load_instrument("flex_1channel_1000", "left")
    ```

=== "OT-2"

    ```python
    # OT-2 single-channel GEN2
    pipette = protocol.load_instrument("p300_single_gen2", "right")
    ```

!!! warning
    Do not load two pipettes on the same mount.

## Compatibility

| Pipette | Flex | OT-2 |
|---------|------|------|
| GEN2    | :opentrons-check: | :opentrons-check: |

{% include "liquid-class-tables/water.md" %}
