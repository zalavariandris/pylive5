from __future__ import annotations
from os import PathLike, fspath
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import PyOpenColorIO as ocio
from .vfxops import ImageRGBA, validate_image_data

def transform_colorspace(
        image_data: ImageRGBA, 
        input_space: str, 
        output_space: str, 
        configuration: ocio.Config | str | PathLike[str] | None = None
    ) -> ImageRGBA:
    import numpy as np
    import PyOpenColorIO as ocio
    validate_image_data(image_data)
    pixels = image_data
    for label, space in (("input_space", input_space), ("output_space", output_space)):
        if not isinstance(space, str) or not space.strip():
            raise ValueError(f"{label} must be a nonempty OCIO color-space name or role.")

    config = configuration
    if config is None:
        config = ocio.GetCurrentConfig()
    elif isinstance(config, (str, PathLike)):
        name = fspath(config)
        if name.startswith("ocio://"):
            config = ocio.Config.CreateFromFile(name)
        elif name in ocio.BuiltinConfigRegistry():
            config = ocio.Config.CreateFromBuiltinConfig(name)
        else:
            config = ocio.Config.CreateFromFile(name)
    elif not isinstance(config, ocio.Config):
        raise TypeError("configuration must be an OCIO Config, path, built-in name, or None.")

    processor = config.getProcessor(input_space, output_space).getDefaultCPUProcessor()
    result = pixels.copy(order="C")
    # Process RGB separately to preserve alpha even for custom OCIO matrices.
    rgb = np.ascontiguousarray(result[..., :3])
    processor.applyRGB(rgb)
    result[..., :3] = rgb
    return result