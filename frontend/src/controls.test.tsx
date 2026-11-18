import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useState } from "react";

import { ChipChoice, DropZone, Segmented, Stepper, Switch, Tabs, ThreadChip } from "./controls";
import { StitchedTitle } from "./motif";

const SMALL = { min: 0, max: 5, step: 1, default: 2 };

describe("Stepper", () => {
  it("steps by the limit's step and stops at the range's ends", () => {
    const onChange = vi.fn();
    const { rerender } = render(<Stepper label="Overlap" limits={SMALL} value="4" onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Increase Overlap" }));
    expect(onChange).toHaveBeenLastCalledWith("5");
    fireEvent.click(screen.getByRole("button", { name: "Decrease Overlap" }));
    expect(onChange).toHaveBeenLastCalledWith("3");

    rerender(<Stepper label="Overlap" limits={SMALL} value="5" onChange={onChange} />);
    expect(screen.getByRole("button", { name: "Increase Overlap" })).toBeDisabled();
    rerender(<Stepper label="Overlap" limits={SMALL} value="0" onChange={onChange} />);
    expect(screen.getByRole("button", { name: "Decrease Overlap" })).toBeDisabled();
  });

  it("sends what is typed as it is, and steps from the default when it is not a number", () => {
    const onChange = vi.fn();
    const { rerender } = render(<Stepper label="Overlap" limits={SMALL} value="2" onChange={onChange} />);

    fireEvent.change(screen.getByRole("spinbutton", { name: "Overlap" }), { target: { value: "9" } });
    expect(onChange).toHaveBeenLastCalledWith("9");

    rerender(<Stepper label="Overlap" limits={SMALL} value="" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Increase Overlap" }));
    expect(onChange).toHaveBeenLastCalledWith("3");
  });

  it("keeps a decimal step free of float noise", () => {
    const onChange = vi.fn();
    const limits = { min: 0, max: 10, step: 0.1, default: 0 };
    render(<Stepper label="Distance" limits={limits} value="0.2" onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Increase Distance" }));
    expect(onChange).toHaveBeenLastCalledWith("0.3");
  });
});

describe("ChipChoice", () => {
  it("fills the field with a chip's value, and shows the chip of the value as chosen", () => {
    const onChange = vi.fn();
    render(<ChipChoice label="Fabric count" presets={[14, 16, 18]} value="16" onChange={onChange} />);

    expect(screen.getByRole("radio", { name: "16" })).toBeChecked();
    expect(screen.getByLabelText("Fabric count")).toHaveValue(16);
    fireEvent.click(screen.getByRole("radio", { name: "18" }));
    expect(onChange).toHaveBeenLastCalledWith("18");
  });

  it("checks no chip for another value, which the field shows", () => {
    render(<ChipChoice label="Fabric count" presets={[14, 16]} value="25" onChange={vi.fn()} />);

    expect(screen.queryByRole("radio", { checked: true })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Fabric count")).toHaveValue(25);
  });
});

describe("DropZone", () => {
  it("takes a file chosen or dropped, and names it once chosen", () => {
    const onChange = vi.fn();
    const file = new File(["png"], "sprite.png", { type: "image/png" });
    const { rerender } = render(<DropZone label="Image" file={null} onChange={onChange} />);

    fireEvent.drop(screen.getByText(/drop it here/).closest("label") as HTMLElement, {
      dataTransfer: { files: [file] },
    });
    expect(onChange).toHaveBeenLastCalledWith(file);

    fireEvent.change(screen.getByLabelText("Image"), { target: { files: [file] } });
    expect(onChange).toHaveBeenCalledTimes(2);

    rerender(<DropZone label="Image" file={file} onChange={onChange} />);
    expect(screen.getByText("sprite.png")).toBeInTheDocument();
  });
});

describe("Segmented and Switch", () => {
  it("names a shown group by its legend and hands back the value chosen", () => {
    const onChange = vi.fn();
    render(
      <Segmented
        legend="Paper"
        showLegend
        options={[
          { value: "A4", label: "A4" },
          { value: "A3", label: "A3" },
        ]}
        value="A4"
        onChange={onChange}
      />,
    );

    const group = screen.getByRole("group", { name: "Paper" });
    expect(group).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "A3" }));
    expect(onChange).toHaveBeenLastCalledWith("A3");
  });

  it("switches a checkbox named by its label", () => {
    const onChange = vi.fn();
    render(<Switch label="Centre lines" checked={false} onChange={onChange} />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Centre lines" }));
    expect(onChange).toHaveBeenLastCalledWith(true);
  });
});

describe("StitchedTitle", () => {
  it("draws every letter of the title, hidden from readers", () => {
    const { container } = render(<StitchedTitle lines={["CROSS-STITCH", "PATTERN MAKER"]} />);

    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelectorAll("path")).toHaveLength(2);
  });

  it("refuses a letter it cannot stitch", () => {
    expect(() => render(<StitchedTitle lines={["Q"]} />)).toThrow(/no stitched letter/);
  });
});


describe("Tabs", () => {
  function Three() {
    const [value, setValue] = useState<"image" | "pattern" | "chart">("image");
    return (
      <Tabs
        label="Settings"
        value={value}
        onChange={setValue}
        tabs={[
          { value: "image", label: "Image", content: <p>image settings</p> },
          { value: "pattern", label: "Pattern", content: <p>pattern settings</p> },
          { value: "chart", label: "Chart", content: <p>chart settings</p> },
        ]}
      />
    );
  }

  function tab(name: string): HTMLElement {
    return screen.getByRole("tab", { name });
  }

  it("shows one tablist, the first tab selected and only its panel, named by it", () => {
    render(<Three />);

    expect(screen.getAllByRole("tablist")).toHaveLength(1);
    expect(tab("Image")).toHaveAttribute("aria-selected", "true");
    expect(tab("Pattern")).toHaveAttribute("aria-selected", "false");
    const panels = screen.getAllByRole("tabpanel");
    expect(panels).toHaveLength(1);
    expect(screen.getByRole("tabpanel", { name: "Image" })).toHaveTextContent("image settings");
    expect(screen.getByText("pattern settings")).not.toBeVisible();
  });

  it("moves along the tabs with the arrow keys, wrapping, and to the ends with Home and End", () => {
    render(<Three />);

    fireEvent.keyDown(tab("Image"), { key: "ArrowRight" });
    expect(tab("Pattern")).toHaveAttribute("aria-selected", "true");
    expect(tab("Pattern")).toHaveFocus();
    expect(screen.getByRole("tabpanel", { name: "Pattern" })).toBeVisible();

    fireEvent.keyDown(tab("Pattern"), { key: "Home" });
    expect(tab("Image")).toHaveFocus();
    fireEvent.keyDown(tab("Image"), { key: "ArrowLeft" });
    expect(tab("Chart")).toHaveAttribute("aria-selected", "true");
    expect(tab("Chart")).toHaveFocus();
    fireEvent.keyDown(tab("Chart"), { key: "Home" });
    fireEvent.keyDown(tab("Image"), { key: "End" });
    expect(tab("Chart")).toHaveFocus();
  });

  it("selects a tab on click and keeps only the selected one in the tab order", () => {
    render(<Three />);

    fireEvent.click(tab("Chart"));

    expect(tab("Chart")).toHaveAttribute("tabindex", "0");
    expect(tab("Image")).toHaveAttribute("tabindex", "-1");
    expect(screen.getByText("chart settings")).toBeVisible();
  });
});

describe("ThreadChip", () => {
  it("shows the thread's code, is named for it, and asks for another on click", () => {
    const onClick = vi.fn();
    render(
      <ThreadChip label="Paint with" thread={{ code: "310", name: "Black", rgb: [0, 0, 0] }} onClick={onClick} />,
    );

    const chip = screen.getByRole("button", { name: "Paint with 310 Black: choose another" });
    expect(chip).toHaveTextContent("310");
    fireEvent.click(chip);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("reads as no thread without one, and can be disabled", () => {
    render(<ThreadChip label="Paint with" thread={null} onClick={vi.fn()} disabled />);

    expect(screen.getByRole("button", { name: "Paint with no thread: choose another" })).toBeDisabled();
  });
});
