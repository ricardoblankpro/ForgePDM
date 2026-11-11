// Decimal string arithmetic keeps presentation rounding independent of binary floats.
export function formatMass(value, shift = 0) {
  const match = String(value).match(/^([+]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/);
  if (!match) throw new Error("Invalid mass");
  const fraction = match[3] || "";
  const exponent = Number(match[4] || 0) + shift - fraction.length;
  let digits = BigInt(match[2] + fraction);
  if (digits === 0n) return "0";
  // Work in thousandths of the requested display unit.
  const power = exponent + 3;
  if (power < 0) {
    const divisor = 10n ** BigInt(-power);
    if (digits < divisor) return "<0.001";
    digits = (digits + divisor / 2n) / divisor;
  } else digits *= 10n ** BigInt(power);
  const whole = digits / 1000n;
  const tail = String(digits % 1000n).padStart(3, "0").replace(/0+$/, "");
  return `${whole}${tail ? "." + tail : ""}`;
}
