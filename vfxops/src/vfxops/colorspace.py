from __future__ import annotations
from os import PathLike, fspath
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import PyOpenColorIO as ocio
from .core import ImageRGBA, validate_image_data

def transform_colorspace(
        image_data: ImageRGBA, 
        input_space: str, 
        output_space: str, 
        configuration: ocio.Config | str | PathLike[str] | None = None
    ) -> ImageRGBA:
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
    # Omit alpha so custom OCIO matrices cannot change the stored alpha plane.
    _, height, width = result.shape
    planes = ocio.PlanarImageDesc(result[0], result[1], result[2], width, height)
    processor.apply(planes)
    return result
