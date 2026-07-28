export function publicApi(): void {}

export const VERSION = "1.0.0";

export default class {
  run(): void {
    start();
  }
}

export { helperA, helperB as aliasB } from "./helpers";
export * from "./everything";
