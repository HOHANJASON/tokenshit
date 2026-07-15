# Billing and balance

## How billing works

NexToken is prepaid: you top up a wallet balance and every API call is
metered against it. The cost of a call is
`input_tokens * input_price + output_tokens * output_price`, using the
per-million-token prices of the model you called.

## Check your spend

The dashboard shows your balance and recent calls. You can also ask this
copilot ("how much did I spend this month?") — it reads the same audited
usage log, including tokens and cost per call.

## Top up your balance

Go to Billing → Top up in the dashboard. Payment methods and redemption
codes are applied instantly; your balance never expires.

## Model pricing

Each model lists an input price and an output price per million tokens on
the Models page. Cheaper models like nxt-local are ideal for development;
switch the `model` field per request to control cost.
