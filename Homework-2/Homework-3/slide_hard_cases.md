# Homework 3 Hard Cases

## Purpose

These three questions are intentionally difficult enough to expose the limits of a prompt-only text-to-SQL system over Bitcoin block data.

## Hard Case 1: Recursive Spend Chains

- Question: Find the earliest block where an output was eventually spent by a transaction whose output was later spent again within 3 more hops, and return the full chain.
- Why it is hard: This requires recursive graph traversal over transaction lineage, which most text-to-SQL systems do not compose reliably.

## Hard Case 2: Rolling Median Change

- Question: For every 100-block window, compute the median transaction output value and find the window with the largest increase versus the previous window.
- Why it is hard: This combines window functions, grouped medians, and second-order comparisons.

## Hard Case 3: Address Reuse Across Versions

- Question: Which output address appears in the greatest number of distinct blocks while also receiving outputs from at least three different transaction versions?
- Why it is hard: This requires multi-table aggregation, distinct counting across two dimensions, and constrained ranking over addresses.
