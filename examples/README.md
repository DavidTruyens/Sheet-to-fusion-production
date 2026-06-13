# Examples

`variants_example.csv` shows the exact shape the add-in expects:

- **Column A is `Name`** — becomes the component name in the assembly.
- Each remaining column header is a **parameter name**, and each row is one variant.
- Cell values include **units** (`50 mm`), because they are written straight into
  the parameter's expression.

> The column names here (`length`, `width`, `height`) are placeholders. Replace them
> with the parameter names in *your* model — or, better, let the add-in generate the
> header for you with **Create Variant Sheet Template**, which reads the names from
> the model's favorite parameters so they always match.

To try it: import this CSV into Google Sheets (**File → Import → Upload**), share it
("Anyone with the link") or publish it to the web as CSV, then paste the link into
**Build Variants Assembly from Sheet**.
