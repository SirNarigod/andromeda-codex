import { App } from "./app";

export function boot(root: HTMLElement): void {
  new App(root).start();
}
