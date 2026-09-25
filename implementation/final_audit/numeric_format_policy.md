# Numeric format policy

Formal JSON retains full computed precision. Presentation layers use: time 3 decimals;
energy 6 decimals; distance 3 decimals; ratios 6 decimals; counts as integers.
Rounding is display-only and never written back to formal JSON.
