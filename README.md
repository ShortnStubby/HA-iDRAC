# HA-iDRAC Project

This repository contains custom Home Assistant add-ons for managing and monitoring Dell PowerEdge servers via their iDRAC interface.

## Available Add-ons

1.  **HA iDRAC Controller (Stable)**
    * Monitors key server metrics (CPU temperature, fan speeds, power consumption) and controls fan speeds based on CPU temperature.
    * For detailed information, installation, and configuration, please see the [**Stable Add-on README](./ha-idrac-controller/README.md)**.

2.  **HA iDRAC Controller (Development Version)**
    * **<font color="orange">⚠️ DEVELOPMENT VERSION - USE WITH CAUTION! ⚠️</font>**
    * This is the active development version, including the latest features and bug fixes, but may also be unstable. Intended for testing and feedback.
    * For detailed information, installation, and configuration, please see the [**Development Add-on README](./ha-idrac-controller-dev/README.md)**.

## Adding this Repository to Home Assistant

To install these add-ons:

1.  In Home Assistant, navigate to **Settings > Add-ons**.
2.  Click on the **"ADD-ON STORE"** button.
3.  Click the **three-dots menu (⋮)** in the top right and select **"Repositories"**.
4.  Add the URL of this repository:
    ```
    [https://github.com/Aesgarth/HA-iDRAC](https://github.com/Aesgarth/HA-iDRAC)
    ```
5.  Click **"ADD"** and then **"CLOSE"**.
6.  The add-ons from this repository will now be available in the store under the name specified in the `repository.yaml` file (e.g., "Aesgarth's Custom iDRAC Add-on"). Select the specific version you wish to install.

## Issues and Contributions

Please report any issues or make contributions via the [GitHub Issues page](https://github.com/Aesgarth/HA-iDRAC/issues), clearly stating which version of the add-on you are using.

## License

This project and its components are under the [MIT License](./LICENSE).