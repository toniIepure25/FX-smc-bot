# Gate C5-A-DQR Provider Parity Protocol

Fallback may be used only after parity passes on healthy Node lineage samples.

| Provider | Source | Timestamp | Side | Flats | Precision |
| --- | --- | --- | --- | --- | --- |
| pinned dukascopy-node | Dukascopy datafeed BI5 | UTC day start + BI5 seconds offset | bid and ask | ignoreFlats=true | USDJPY decimalFactor=1000 |
| native-bi5-browser-ua | Dukascopy datafeed BI5 | UTC day start + BI5 seconds offset | bid and ask | ignoreFlats=true | USDJPY integer scale=1000 |
