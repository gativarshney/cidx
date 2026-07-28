export function parse(input: string): Config;
export function parse(input: Buffer): Config;
export function parse(input: unknown): Config {
  return build(input);
}
