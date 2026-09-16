// Shim de compatibilidad: permite `node src/gateway.js` mientras el runner antiguo
// (cargado en memoria) siga apuntando a src/. Ejecuta el codigo TypeScript nuevo.
// Se puede eliminar tras desplegar el build en dist/.
import { runGateway } from './gateway.ts';

runGateway();
