$ErrorActionPreference = "Stop"

docker exec info7500-bitcoin-node /src/bitcoin/build/bin/bitcoin-cli -datadir=/data getblockhash 0
