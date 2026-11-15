import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChipChoice, DropZone, Segmented, Stepper, Switch } from "./controls";
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
