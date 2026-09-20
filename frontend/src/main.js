import "./index.css";

import { createApp } from "vue";
import {
  Autocomplete,
  Badge,
  Button,
  Dialog,
  FeatherIcon,
  FormControl,
  frappeRequest,
  resourcesPlugin,
  setConfig,
} from "frappe-ui";

import App from "./App.vue";
import router from "./router";

const app = createApp(App);

setConfig("resourceFetcher", frappeRequest);

app.use(router);
app.use(resourcesPlugin);

app.component("Autocomplete", Autocomplete);
app.component("Badge", Badge);
app.component("Button", Button);
app.component("Dialog", Dialog);
app.component("FeatherIcon", FeatherIcon);
app.component("FormControl", FormControl);

app.mount("#app");
