// Shim de compatibilidad: permite `node src/exit.js` mientras el runner antiguo
// (cargado en memoria) siga apuntando a src/. Ejecuta el codigo TypeScript nuevo.
// Se puede eliminar tras desplegar el build en dist/.
import { runExit } from './exit.ts';

runExit();
