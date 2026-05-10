## Observaciones sobre los datos (dataset dummy)

### Lead Penetration — valores anómalos
- Se detectaron valores de Lead Penetration que superan el rango esperado (0-100%)
- Ejemplos: Sur de Quito (393.9), Valle de los Chillos (158.6)
- Causa probable: los datos fueron anonimizados y randomizados sin respetar la escala de la métrica
- En producción: agregar validación de rango por tipo de métrica antes de mostrar al usuario
- Definición real: Tiendas activas / (Tiendas activas + Tiendas potenciales + Tiendas que se fueron) → siempre entre 0% y 100%

### Gross Profit UE — no es porcentaje
- A diferencia del resto de métricas, Gross Profit UE es dinero por orden (no porcentaje)
- No se multiplica por 100 en los resultados
- El bot ya maneja esto correctamente vía el system prompt

### L0W — semana parcial
- L0W representa la semana actual que puede no haber terminado
- Caídas en L0W vs L1W pueden ser normales si la semana está incompleta
- El bot ya advierte esto cuando detecta caídas en la semana actual