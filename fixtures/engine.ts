// A miniature layout + camera engine, synthetic on purpose: no project, asset or path
// from any real repository appears here. It exists so the verifier has something to be
// right or wrong about without depending on a browser.
//
// The shape is the one that hides bugs in a TypeScript -> Python port: a fractional
// scale, a window centred in a canvas, and a camera law whose output is consumed at
// every frame.

export const CANVAS_W = 1080;
export const CANVAS_H = 1920;
export const VIEW_W = 864;
export const VIEW_H = 960;

// Native plate 768 x 1344 scaled by a non-integer factor. 985.714... is deliberate:
// a port that quantises the scaled canvas to 986 introduces a 0.03% anisotropy.
export const SCALE = 1725 / 1344;
export const PLATE_W = 768 * SCALE;
export const PLATE_H = 1344 * SCALE;

export const OFFSET_X = Math.floor((CANVAS_W - VIEW_W) / 2);
export const OFFSET_Y = Math.floor((CANVAS_H - VIEW_H) / 2);

// Camera laws. `ease` is the u^3 law, `travel` the smoothstep-shaped ramp, `pulse`
// concentrates speed near the ends and is the case a linear budget gets wrong.
export const ease = (u: number) => u * u * u;
export const travel = (u: number) => 3 * u * u - 2 * u * u * u;
export const pulse = (u: number) => 17.4 * (u ** 3 - 3 * u ** 2 + 3 * u);

// Half-pixel helpers: JS Math.round rounds half towards +Infinity, which is not what
// Python's round() does. A port that uses round() diverges at exactly .5.
export const halfUp = (v: number) => Math.floor(v + 0.5);
export const snapLow = (v: number) => Math.floor(v);

// The shapes that a line-based reader gets wrong, reproduced here so the regression
// travels with the fixture: an object literal behind `as const`, an arrow whose body
// spans lines and returns an object, a default obtained with `??`, a body that declares
// variables of its own, and a body that is a block.
export const BOX = { w: 1080, h: 1920 } as const;
export const VIEW = { w: 864, h: 960 } as const;

export const rectView = (y?: number) => ({
  left: (BOX.w - VIEW.w) / 2,
  top: y ?? (BOX.h - VIEW.h) / 2,
  width: VIEW.w,
  height: VIEW.h,
});

export const NEAR = [1.8, 3.0, 4.2] as const;

// Declared, and deliberately outside what the reader evaluates: a `reduce` is a loop, not
// an arithmetic expression. Comparing it must report a gap, never a pass.
export const nearestNode = (v: number) =>
  NEAR.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a));

// A block body with locals: `m`, `d` and `gap` must never surface as module anchors.
export const onNode = (v: number): boolean => {
  const m = v / 1.2;
  const d = Math.abs(m - Math.round(m));
  const gap = d * 1.2;
  return gap < 0.15;
};
