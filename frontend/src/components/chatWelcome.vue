<script setup lang="ts">
import welcomeImage from "@/assets/welcome.png";
</script>

<template>
  <div class="welcome">
    <img class="welcome-image" :src="welcomeImage" alt="" width="1774" height="887" />
    <h2>世界为你敞开，向我提问吧！</h2>
  </div>
</template>

<style scoped lang="scss">
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: clamp(40px, 12vh, 120px) 0 48px;
  text-align: center;

  .welcome-image {
    display: block;
    width: min(560px, 100%);
    height: auto;
    object-fit: contain;
  }

  h2 {
    margin: 0;
    color: #30343b;
    font-family: inherit;
    font-size: clamp(18px, 2vw, 22px);
    font-weight: 600;
    line-height: 1.6;
    letter-spacing: normal;
    text-wrap: balance;
  }
}
</style>
