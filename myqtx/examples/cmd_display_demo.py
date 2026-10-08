"""Display data from the terminal using the shared, automatically started stage."""

import numpy as np
from rich.console import Console
from rich.prompt import Prompt
from myqtx import cmdstage as stage


def make_image(frame: int) -> np.ndarray:
    y, x = np.indices((600, 900))
    red = (x + frame * 25) % 256
    green = (y + frame * 15) % 256
    blue = ((x + y) // 2 + frame * 35) % 256
    return np.stack((red, green, blue), axis=-1).astype(np.uint8)


def main() -> None:
    console = Console()
    console.print("Display an image, comparison, HTML, or Markdown.")
    console.print("The viewer starts when needed. Close it and display again to restart.")
    frame = 0
    while True:
        command = Prompt.ask(
            "Command",
            choices=["show", "compare", "html", "markdown", "clear", "close", "quit"],
            default="show",
        )
        match command:
            case "quit":
                stage.close()
                return
            case "clear":
                stage.clear()
            case "close":
                stage.close()
            case "html":
                stage.show(stage.HTML(
                    "<h1>cmdstage</h1>"
                    "<p>Display <b>HTML</b> from your command line.</p>"
                ))
            case "markdown":
                stage.show(stage.Markdown(
                    "# cmdstage\n\nDisplay **Markdown** from your command line."
                ))
            case "show" | "compare":
                image = make_image(frame)
                if command == "compare":
                    stage.show(stage.ImageCompare(image, image[:, ::-1]))
                else:
                    stage.show(stage.Image(data=image))
                console.print(f"[green]Displayed frame {frame}[/green]")
                frame += 1


if __name__ == "__main__":
    main()
