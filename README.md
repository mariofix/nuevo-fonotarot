# nuevo-fonotarot

105605273

Nuevo Sitio Fonotarot

```sql
  SADD agents:all 01 06 12 13 14 15

  HSET agent:01 name Paulina
  HSET agent:01 option 01
  HSET agent:01 number 7001
  HSET agent:01 status busy
  HSET agent:01 since 0
  EXPIRE agent:01 90

  HSET agent:06 name Paola
  HSET agent:06 option 06
  HSET agent:06 number 7006
  HSET agent:06 status available
  HSET agent:06 since 0
  EXPIRE agent:06 90

  HSET agent:12 name Alvaro
  HSET agent:12 option 12
  HSET agent:12 number 7012
  HSET agent:12 status busy
  HSET agent:12 since 0
  EXPIRE agent:12 90

  HSET agent:13 name Simone
  HSET agent:13 option 13
  HSET agent:13 number 7013
  HSET agent:13 status busy
  HSET agent:13 since 0
  EXPIRE agent:13 90

  HSET agent:14 name Alex
  HSET agent:14 option 14
  HSET agent:14 number 7014
  HSET agent:14 status busy
  HSET agent:14 since 0
  EXPIRE agent:14 90

  HSET agent:15 name Violeta
  HSET agent:15 option 15
  HSET agent:15 number 7015
  HSET agent:15 status available
  HSET agent:15 since 0
  EXPIRE agent:15 90

  Then verify:

  SMEMBERS agents:all
  HGETALL agent:15
```
