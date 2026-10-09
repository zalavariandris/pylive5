import rich

rich.print("Hello, Rich!")
from myqtx import cmdstage as stage, Image, ImageCompare
from rich.prompt import Prompt


def authenticate_openai():
    ...

def read_image(image_path: str):
    ...

def colortransform(img, inputspace, outputspace):
    ...

def enchance_prompt(img, prompt: str):
    ...

def gpt_retouch(img, prompt: str):
    ...

def write_image(img, output_path: str):
    ...

# STATE
## inputs
IMAGE_PATH = ""
INPUT_SPACE = "SONY"
PROMPT = """"\

"""
OUTPUT_PATH =  ""

## intermadiate
authenticated = False
footage = None
footage_rec709 = None
revised_prompt = None
retouched_footage = None



def main():
    """GPT Image Cleanup Workflow"""
    # 1. Authentication
    from rich.status import Status
    while True:
        with Status("Authenticating with OpenAI...", spinner="dots") as status:
            try:
                authenticate_openai()
                status.update("Authentication successful!")
                break

            except Exception as e:
                status.update(f"Authentication failed: {e}")

    # 2. Drop image for retouch
    #    read and apply colortransform
    IMAGE_PATH = Prompt.ask("Enter the path to the image file")
    INPUT_SPACE = Prompt.ask("Enter the input color space", default="ColorSpace.SONY")

    with Status("Reading image...", spinner="dots") as status:
        try:
            footage = read_image(IMAGE_PATH)
            footage_rec709 = colortransform(footage, INPUT_SPACE, 'ColorSpace.Rec709')
            status.update("Image read successfully!")
        except Exception as e:
            status.update(f"Failed to read image: {e}")

    stage.show(Image(footage_rec709)) # this is non blocking

    # 3. Retouch the image using a prompt
    #    enchance prompt
    PROMPT = Prompt.ask("Enter the retouch instructions")
    with Status("Applying retouch...", spinner="dots") as status:
        try:
            revised_prompt = enchance_prompt(footage_rec709, PROMPT)
            retouched_footage = gpt_retouch(footage_rec709, revised_prompt)
            status.update("Retouch applied successfully!")
        except Exception as e:
            status.update(f"Failed to apply retouch: {e}")

    stage.show(ImageCompare(footage_rec709, retouched_footage)) # this is non blocking

    # 4. save the retouched image
    OUTPUT_PATH = Prompt.ask("Enter the output path for the retouched image", default="retouched_image.png")
    with Status("Saving retouched image...", spinner="dots") as status:
        try:
            write_image(retouched_footage, OUTPUT_PATH)
            status.update("Retouched image saved successfully!")
        except Exception as e:
            status.update(f"Failed to save retouched image: {e}")
