import { createStart } from '@tanstack/react-start'

// Framework touchpoint: global request middleware and server function middleware hang off this instance.
export const startInstance = createStart(() => ({}))
