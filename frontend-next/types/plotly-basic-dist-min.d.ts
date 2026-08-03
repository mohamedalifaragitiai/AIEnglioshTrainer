/**
 * Minimal typings for the Plotly basic bundle.
 *
 * Hand-written rather than pulling `@types/plotly.js`: that package types the
 * *full* library — thousands of attributes for trace types this bundle does not
 * contain — and would let a `scatterpolar` typecheck cleanly and then fail at
 * runtime. Declaring only the three calls the dashboard makes keeps the types
 * honest about what is actually shipped.
 */
declare module "plotly.js-basic-dist-min" {
  type Data = Record<string, unknown>;
  type Layout = Record<string, unknown>;
  type Config = Record<string, unknown>;

  export function react(
    el: HTMLElement,
    data: Data[],
    layout?: Layout,
    config?: Config,
  ): Promise<HTMLElement>;

  export function newPlot(
    el: HTMLElement,
    data: Data[],
    layout?: Layout,
    config?: Config,
  ): Promise<HTMLElement>;

  export function purge(el: HTMLElement): void;

  const Plotly: {
    react: typeof react;
    newPlot: typeof newPlot;
    purge: typeof purge;
  };
  export default Plotly;
}
