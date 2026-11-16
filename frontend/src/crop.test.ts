import { describe, expect, it } from "vitest";

import { boxFromDrag, boxFromField, cropField, percentRect } from "./crop";

const SHOWN = { width: 400, height: 200 };
const NATURAL = { width: 1000, height: 500 };

describe("boxFromDrag", () => {
  it("maps a drag on the shown image to image pixels", () => {
    expect(boxFromDrag({ x: 40, y: 20 }, { x: 200, y: 120 }, SHOWN, NATURAL)).toEqual({
      left: 100,
      top: 50,
      right: 500,
      bottom: 300,
    });
  });

  it("clamps a drag ending outside the shown image to its edge", () => {
    expect(boxFromDrag({ x: 40, y: 20 }, { x: 450, y: -30 }, SHOWN, NATURAL)).toEqual({
      left: 100,
      top: 0,
      right: 1000,
      bottom: 50,
    });
  });

  it("gives the same box whichever way the drag goes", () => {
    const forward = boxFromDrag({ x: 40, y: 20 }, { x: 200, y: 120 }, SHOWN, NATURAL);
    expect(boxFromDrag({ x: 200, y: 120 }, { x: 40, y: 20 }, SHOWN, NATURAL)).toEqual(forward);
  });

  it("gives no box for a drag of under one image pixel", () => {
    expect(boxFromDrag({ x: 40, y: 20 }, { x: 40.2, y: 120 }, SHOWN, NATURAL)).toBeNull();
    expect(boxFromDrag({ x: 40, y: 20 }, { x: 200, y: 20.3 }, SHOWN, NATURAL)).toBeNull();
  });
});

describe("the crop field", () => {
  it("spells a box as left,top,right,bottom and reads it back", () => {
    const box = { left: 100, top: 50, right: 500, bottom: 300 };
    expect(cropField(box)).toBe("100,50,500,300");
    expect(boxFromField("100,50,500,300")).toEqual(box);
    expect(boxFromField("")).toBeNull();
  });

  it("draws a box in percent of the image", () => {
    expect(percentRect({ left: 100, top: 50, right: 500, bottom: 300 }, NATURAL)).toEqual({
      left: 10,
      top: 10,
      right: 50,
      bottom: 60,
    });
  });
});
