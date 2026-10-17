A collection of pure functions for VFX operations.

Images use **planar, channel-first `(channels, height, width)` arrays** with
`IMAGE_DTYPE = np.dtype(np.float32)`. `Image` names the general array type;
`ImageRGBA` describes `(4, height, width)` in R, G, B, A order with straight alpha.
Color values may be negative or greater than one. Size arguments remain
`(width, height)`, and positions remain `(x, y)`.

New pixel buffers are C-contiguous, so each channel is contiguous. Crops may
return strided views into the original planes. Most operations preserve their
inputs; `paste` explicitly writes into its destination in place.

Use `image[:3]` for RGB, `image[3]` for alpha, and `image[:, y, x]` for a pixel.
RGBA color/compositing operations validate four channels; cropping, affine
transforms, resizing, clipping, and pasting support arbitrary channel counts.
Gaussian blur accepts RGB/RGBA and preserves an existing alpha plane.

`from_interleaved` and `to_interleaved` explicitly convert between float32 HWC
and CHW storage. They do not normalize integers, change channel order, or apply
color transforms. For an external uint8 RGB(A) array, normalize to float32
before calling `from_interleaved`.

OpenCV filters and transforms operate on individual planes. OpenColorIO uses
`PlanarImageDesc`. Image/video readers return planar RGBA, preserving floating
HDR values; encoders pack and quantize at the external library boundary.

This is a breaking layout change from HWC. Custom nodes must use CHW indexing
and reshape per-channel parameters to `(channels, 1, 1)` for broadcasting.
The PyFlow viewer expects planar arrays. Standalone myqtx viewers retain their
HWC default: use `DisplayWidget(channel_axis=0)` for planar images, or provide
`DisplayWidget.Image(data, channel_axis=0)`. A custom HWC result can be displayed
in PyFlow with `DisplayWidget.Image(data, channel_axis=-1)`.
