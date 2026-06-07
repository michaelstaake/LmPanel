const GGUF_SHARD_PATTERN = /^(.+)-(\d{5})-of-(\d{5})\.gguf$/i;

type ParsedShard = {
  prefix: string;
  index: number;
  total: number;
  fileName: string;
};

function parseGgufShardName(fileName: string): ParsedShard | null {
  const match = GGUF_SHARD_PATTERN.exec(fileName);
  if (!match) {
    return null;
  }

  const [, prefix, indexText, totalText] = match;
  const index = Number(indexText);
  const total = Number(totalText);
  if (!Number.isInteger(index) || !Number.isInteger(total) || index < 1 || total < 1 || index > total) {
    return null;
  }

  return { prefix, index, total, fileName };
}

export function validateModelUploadFiles(fileNames: string[]): string | null {
  if (fileNames.length <= 1) {
    const fileName = fileNames[0];
    if (!fileName) {
      return "Choose a .gguf file to upload.";
    }
    if (!fileName.toLowerCase().endsWith(".gguf")) {
      return "Only .gguf model files are supported.";
    }
    return null;
  }

  const shards = fileNames.map((fileName) => parseGgufShardName(fileName));
  if (shards.some((shard) => shard === null)) {
    return "Multiple uploads must all be sharded GGUF files (for example, *-00001-of-00002.gguf).";
  }

  const prefixes = new Set(shards.map((shard) => shard!.prefix.toLowerCase()));
  const totals = new Set(shards.map((shard) => shard!.total));
  if (prefixes.size !== 1 || totals.size !== 1) {
    return "All shard files must share the same model prefix and shard count.";
  }

  const total = shards[0]!.total;
  if (fileNames.length !== total) {
    return `Expected ${total} shard files but selected ${fileNames.length}.`;
  }

  const indices = shards.map((shard) => shard!.index).sort((left, right) => left - right);
  const expected = Array.from({ length: total }, (_, index) => index + 1);
  if (indices.some((index, position) => index !== expected[position])) {
    return "Shard upload must include every part from 00001 through the final shard.";
  }

  return null;
}

export function formatShardStatus(shardCount: number | null | undefined, shardsComplete: boolean | undefined, missingShards: string[] | undefined): string | null {
  if (!shardCount || shardCount < 2) {
    return null;
  }

  const present = shardCount - (missingShards?.length ?? 0);
  if (shardsComplete) {
    return `${present}/${shardCount} shards`;
  }

  const missingLabel = missingShards?.length ? ` — missing ${missingShards.join(", ")}` : "";
  return `${present}/${shardCount} shards${missingLabel}`;
}
