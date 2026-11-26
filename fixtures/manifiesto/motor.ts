// The shapes a manifest exists for, synthetic on purpose: no project, asset or path from
// any real repository appears here.
//
// Two containers whose members are the same two numbers at different addresses (an object
// here, a tuple in the reference), one vector renamed on the Python side, and one anchor
// the source declares that nobody measures -- the case a manifest has to count instead of
// swallowing.

export const CUADRO = { ancho: 1080, alto: 1920 } as const;
export const VENTANA = { ancho: 864, alto: 960 } as const;

// Renamed on the other side: `NUDOS_S5` here, `RAMPA_S5` in the reference.
export const NUDOS_S5 = [0.0, 0.25, 0.5, 0.75, 1.0] as const;

// Declared and deliberately outside the manifest: a source may hold more than the contract
// measures, and that is not a divergence.
export const SIN_PAR = 42;
