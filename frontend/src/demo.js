export const isStaticDemo = import.meta.env.MODE === 'demo'
export const demoRepositories = ['scikit-learn/scikit-learn', 'pandas-dev/pandas']

export async function loadDemoRepository(repository) {
  const { default: repositories } = await import('./demoData.json')
  if (!Object.hasOwn(repositories, repository)) {
    throw new Error('Choose one of the example repositories.')
  }
  return repositories[repository]
}
