export interface Config {
  port: number;
  onReady(): void;
}

export type Result<T> = { ok: true; value: T } | { ok: false };

export enum Level {
  Info,
  Warn,
}

const active: Config = load();
