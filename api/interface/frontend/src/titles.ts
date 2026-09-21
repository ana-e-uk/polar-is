import type { Catalog, Dataset, Repository } from "./types";

export const fallbackTitle = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ").replace(/\b\w/g, (character) => character.toUpperCase());

export function repositoryTitle(repository: Repository): string {
  return repository.display_name ?? fallbackTitle(repository.name);
}

export function repositoryName(catalog: Catalog, repository: string): string {
  return catalog.frontend_titles.repository?.[repository]
    ?? catalog.repositories.find((item) => item.name === repository)?.display_name
    ?? fallbackTitle(repository);
}

export function datasetName(catalog: Catalog, repository: string, dataset: string): string {
  return catalog.repositories
    .find((item) => item.name === repository)
    ?.datasets.find((item) => item.name === dataset)
    ?.display_name
    ?? fallbackTitle(dataset);
}

export function variableTitle(catalog: Catalog, variable: string): string {
  return catalog.frontend_titles.variable?.[variable] ?? fallbackTitle(variable);
}

export function genericResolutionTitle(coarsenessFactor: number): string {
  return coarsenessFactor === 1 ? "Source" : `Coarsen-${coarsenessFactor}`;
}

export function spatialResolutionTitle(
  catalog: Catalog,
  dataset: Dataset | undefined,
  coarsenessFactor: number,
): string {
  if (!dataset) return genericResolutionTitle(coarsenessFactor);
  const sourceResolution = dataset.grid?.resolution;
  if (!sourceResolution?.length) return genericResolutionTitle(coarsenessFactor);
  const key = String(sourceResolution[0]);
  const coarsenessKey = coarsenessFactor === 1 ? "source" : `coarsen-${coarsenessFactor}`;
  const displayed = catalog.frontend_titles.resolution?.[key]?.[coarsenessKey];
  if (!displayed?.length) return genericResolutionTitle(coarsenessFactor);
  const units = dataset.grid?.units;
  return `${displayed.join(" × ")}${units ? ` ${units}` : ""}`;
}
